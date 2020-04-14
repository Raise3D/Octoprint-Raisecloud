$(function() {
  function RaiseCloudViewModel(parameters) {
    var self = this;
    self.settings = parameters[0];
    self.loginState = parameters[1];
    self.userName = ko.observable(""); //null while views are being rendered
    self.groupName = ko.observable("");
    self.groupOwner = ko.observable("");
    self.showBind = ko.observable(true);
    self.showInput = ko.observable(false);
    self.fileName = ko.observable("");
    //self.printer_name = ko.observable("raisecloud_variables.printer_name");
    self.printer_name = ko.observable("");
    self.disabled = ko.observable(true);
    self.checked = ko.observable(false);

    self.turnRaise = function() {
      window.open("http://alpha.raise3d.com/raise3d.html");
    };
    // 弹框显示
    self.turnPrivacy = function() {
      $("#privacy_model").show();
      $(".container_fluid").addClass("background");
    };
    //弹框隐藏
    self.privacyCancel = function() {
      $("#privacy_model").hide();
      $(".container_fluid").removeClass("background");
    };

    self.uploadFile = function() {
      let fileName = $("#fileUpload")[0].files[0].name;
      let fileSize = $("#fileUpload")[0].files[0].size;
      let extName = fileName
        .substr(fileName.lastIndexOf(".") + 1)
        .toLowerCase();
      if (extName != "raisepem") {
        $("#bindPageMsg")
          .text("Please choose key file")
          .show(200)
          .delay(3000)
          .hide(500);
        self.fileName("");
        $("#fileUpload").val("");
      } else if (fileSize > 2 * 1024) {
        $("#bindPageMsg")
          .text("The upload key files must not be larger than 2kb")
          .show(200)
          .delay(3000)
          .hide(500);
        self.fileName("");
        $("#fileUpload").val("");
      } else {
        self.fileName(fileName);
        self.disabled(false);
      }
    };

    // 开始绑定
    self.bind = function() {
      if (!self.checked()) {
        $("#bindPageMsg")
          .text("Please agree to privacy policy and service agreement")
          .show(200)
          .delay(3000)
          .hide(500);
      } else if (!self.fileName()) {
        $("#bindPageMsg")
          .text("Please choose key file")
          .show(200)
          .delay(3000)
          .hide(500);
      } else {
        var fileObj = document.getElementById("fileUpload").files[0];

        var formData = new FormData();
        console.log("file bind");
        formData.append("file", fileObj);
        $.ajax({
          type: "POST",
          contentType: false,
          url: PLUGIN_BASEURL + "raisecloud/login",
          data: formData,
          processData: false,
          dataType: "json",
          success: function(data) {
            if (data.status == "failed") {
              self.disabled(false);
              window.alert("failed");
              $("#bindPageMsg")
                .text("bind error")
                .show(200)
                .delay(3000)
                .hide(500);
            } else {
              self.showBind(false);
              self.checked(false);
              self.fileName("");
              $("#fileUpload").val("");
              self.userName(data.user_name);
              self.groupName(data.group_name);
              self.groupOwner(data.group_owner);
              self.printer_name(data.printer_name)
              $("#bindPageMsg")
                .text("bind successfully")
                .show(200)
                .delay(3000)
                .hide(500);
            }
          },
          error: function(error) {
            self.disabled(false);
            $("#bindPageMsg")
              .text("bind error")
              .show(200)
              .delay(3000)
              .hide(500);
          }
        });
      }
    };
    self.editPrintName = function() {
      self.showInput(true);
    };
    (function() {
      $.ajax({
        type: "GET",
        contentType: "application/json; charset=utf-8",
        url: PLUGIN_BASEURL + "raisecloud/status",
        data: {},
        dataType: "json",
        success: function(data) {
          if (data.status == "logout") {
            console.log("user logout");
            self.showBind(true);
            console.log(self.showBind());
          } else {
            console.log("user login");
            self.showBind(false);
            self.userName(data.user_name);
            self.groupName(data.group_name);
            self.groupOwner(data.group_owner);
            self.printer_name(data.printer_name);
            console.log(self.showBind());
          }
        },
        error: function(error) {}
      });
    })();
    //edit文本框的blur事件
    self.onPrintName = function() {
      if (!$(".input").val()) {
        $("#successPageMsg")
          .text("Value cannot be empty")
          .show(200)
          .delay(3000)
          .hide(500);
      } else {
        $.ajax({
          type: "POST",
          contentType: "application/json; charset=utf-8",
          url: PLUGIN_BASEURL + "raisecloud/printer",
          data: JSON.stringify({
            printer_name: $(".input").val()
          }),
          dataType: "json",
          success: function(data) {
            if (data.status == "failed") {
              console.log("modify printer name ...");
              console.log(self.printer_name());
              self.showInput(true);
              $("#successPageMsg")
                .text(data.msg)
                .show(200)
                .delay(3000)
                .hide(500);
            } else {
              console.log("modify printer name ...");
              console.log(self.printer_name());
              self.showInput(false);
              self.printer_name($(".input").val());
            }
          },
          error: function(error) {
            $("#successPageMsg")
              .text("error")
              .show(200)
              .delay(3000)
              .hide(500);
          }
        });
      }
    };

    //unbind
    self.unbind = function() {
      console.log("unbind");
      self.showBind(true);
      $.ajax({
        type: "POST",
        contentType: "application/json; charset=utf-8",
        url: PLUGIN_BASEURL + "raisecloud/logout",
        data: {},
        dataType: "json",
        success: function(data) {
          if (data.status == "logout") {
            self.checked(false);
            self.fileName("");
            $("#fileUpload").val("");
            self.showBind(true);
            console.log(self.showBind());

          } else {
            self.showBind(false);
            console.log(self.showBind());
            $("#successPageMsg")
              .text("Unbind error")
              .show(200)
              .delay(3000)
              .hide(500);
          }
        },
        error: function(error) {
          console.log(self.showBind());
          $("#successPageMsg")
            .text("Unbind error")
            .show(200)
            .delay(3000)
            .hide(500);
        }
      });
    };
    /* Event */
    self.onDataUpdaterPluginMessage = function (plugin, message) {
        if (plugin == "RaiseCloud") {
            switch (message.event) {
                case "Logout":
                    self.showBind(true);
                    break;
                default:
                    break;
            }
        }
    };

  }

  // view model class, parameters for constructor, container to bind to
  OCTOPRINT_VIEWMODELS.push([
    RaiseCloudViewModel,
    ["settingsViewModel", "loginStateViewModel"],
    ["#settings_plugin_raisecloud"]
  ]);
});
